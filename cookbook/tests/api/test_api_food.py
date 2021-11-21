import json

import pytest
from django.contrib import auth
from django.urls import reverse
from django_scopes import scope, scopes_disabled
from pytest_factoryboy import LazyFixture, register

from cookbook.models import Food, FoodInheritField, Ingredient, ShoppingList, ShoppingListEntry
from cookbook.tests.factories import (FoodFactory, IngredientFactory, ShoppingListEntryFactory,
                                      SupermarketCategoryFactory)

#    ------------------ IMPORTANT -------------------
#
#  if changing any capabilities associated with food
#  you will need to ensure that it is tested against both
#  SqlLite and PostgresSQL
#  adding load_env() to settings.py will enable Postgress access
#
#    ------------------ IMPORTANT -------------------

LIST_URL = 'api:food-list'
DETAIL_URL = 'api:food-detail'
MOVE_URL = 'api:food-move'
MERGE_URL = 'api:food-merge'
if (Food.node_order_by):
    node_location = 'sorted-child'
else:
    node_location = 'last-child'


register(FoodFactory, 'obj_1', space=LazyFixture('space_1'))
register(FoodFactory, 'obj_2', space=LazyFixture('space_1'))
register(FoodFactory, 'obj_3', space=LazyFixture('space_2'))
register(SupermarketCategoryFactory, 'cat_1', space=LazyFixture('space_1'))


# @pytest.fixture
# def true():
#     return True


@pytest.fixture
def false():
    return False


@pytest.fixture
def non_exist():
    return {}


@pytest.fixture()
def obj_tree_1(request, space_1):
    try:
        params = request.param
    except AttributeError:
        params = {}
    objs = []
    objs.extend(FoodFactory.create_batch(3, space=space_1, **params))  # request.param is a magic variable
    objs[0].move(objs[1], node_location)
    objs[1].move(objs[2], node_location)
    return Food.objects.get(id=objs[1].id)  # whenever you move/merge a tree it's safest to re-get the object


@pytest.mark.parametrize("arg", [
    ['a_u', 403],
    ['g1_s1', 403],
    ['u1_s1', 200],
    ['a1_s1', 200],
])
def test_list_permission(arg, request):
    c = request.getfixturevalue(arg[0])
    assert c.get(reverse(LIST_URL)).status_code == arg[1]


def test_list_space(obj_1, obj_2, u1_s1, u1_s2, space_2):
    assert json.loads(u1_s1.get(reverse(LIST_URL)).content)['count'] == 2
    assert json.loads(u1_s2.get(reverse(LIST_URL)).content)['count'] == 0

    obj_1.space = space_2
    obj_1.save()

    assert json.loads(u1_s1.get(reverse(LIST_URL)).content)['count'] == 1
    assert json.loads(u1_s2.get(reverse(LIST_URL)).content)['count'] == 1


def test_list_filter(obj_1, obj_2, u1_s1):
    r = u1_s1.get(reverse(LIST_URL))
    assert r.status_code == 200
    response = json.loads(r.content)
    assert response['count'] == 2

    assert obj_1.name in [x['name'] for x in response['results']]
    assert obj_2.name in [x['name'] for x in response['results']]
    assert response['results'][0]['name'] < response['results'][1]['name']

    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?page_size=1').content)
    assert len(response['results']) == 1

    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?limit=1').content)
    assert len(response['results']) == 1

    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?query=''&limit=1').content)
    assert len(response['results']) == 1

    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?query=chicken').content)
    assert response['count'] == 0

    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?query={obj_1.name[:-4]}').content)
    assert response['count'] == 1


@pytest.mark.parametrize("arg", [
    ['a_u', 403],
    ['g1_s1', 403],
    ['u1_s1', 200],
    ['a1_s1', 200],
    ['g1_s2', 403],
    ['u1_s2', 404],
    ['a1_s2', 404],
])
def test_update(arg, request, obj_1):
    c = request.getfixturevalue(arg[0])
    r = c.patch(
        reverse(
            DETAIL_URL,
            args={obj_1.id}
        ),
        {'name': 'new'},
        content_type='application/json'
    )
    response = json.loads(r.content)
    assert r.status_code == arg[1]
    if r.status_code == 200:
        assert response['name'] == 'new'


@pytest.mark.parametrize("arg", [
    ['a_u', 403],
    ['g1_s1', 403],
    ['u1_s1', 201],
    ['a1_s1', 201],
])
def test_add(arg, request, u1_s2):
    c = request.getfixturevalue(arg[0])
    r = c.post(
        reverse(LIST_URL),
        {'name': 'test'},
        content_type='application/json'
    )
    response = json.loads(r.content)
    assert r.status_code == arg[1]
    if r.status_code == 201:
        assert response['name'] == 'test'
        r = c.get(reverse(DETAIL_URL, args={response['id']}))
        assert r.status_code == 200
        r = u1_s2.get(reverse(DETAIL_URL, args={response['id']}))
        assert r.status_code == 404


def test_add_duplicate(u1_s1, u1_s2, obj_1, obj_3):
    assert json.loads(u1_s1.get(reverse(LIST_URL)).content)['count'] == 1
    assert json.loads(u1_s2.get(reverse(LIST_URL)).content)['count'] == 1
    r = u1_s1.post(
        reverse(LIST_URL),
        {'name': obj_1.name},
        content_type='application/json'
    )
    response = json.loads(r.content)
    assert r.status_code == 201
    assert response['id'] == obj_1.id
    assert response['name'] == obj_1.name
    assert json.loads(u1_s1.get(reverse(LIST_URL)).content)['count'] == 1

    r = u1_s2.post(
        reverse(LIST_URL),
        {'name': obj_1.name},
        content_type='application/json'
    )
    response = json.loads(r.content)
    assert r.status_code == 201
    assert response['id'] != obj_1.id
    assert json.loads(u1_s2.get(reverse(LIST_URL)).content)['count'] == 2


def test_delete(u1_s1, u1_s2, obj_1, obj_tree_1):
    with scopes_disabled():
        assert Food.objects.count() == 4

    r = u1_s2.delete(
        reverse(
            DETAIL_URL,
            args={obj_1.id}
        )
    )
    assert r.status_code == 404
    with scopes_disabled():
        assert Food.objects.count() == 4

    # should delete self and child, leaving parent
    r = u1_s1.delete(
        reverse(
            DETAIL_URL,
            args={obj_tree_1.id}
        )
    )

    assert r.status_code == 204
    with scopes_disabled():
        assert Food.objects.count() == 2
        assert Food.find_problems() == ([], [], [], [], [])


def test_integrity(u1_s1, recipe_1_s1):
    with scopes_disabled():
        assert Food.objects.count() == 10
        assert Ingredient.objects.count() == 10
        f_1 = Food.objects.first()

    # deleting food will fail because food is part of recipe
    r = u1_s1.delete(
        reverse(
            DETAIL_URL,
            args={f_1.id}
        )
    )
    assert r.status_code == 403

    with scopes_disabled():
        i_1 = f_1.ingredient_set.first()
        # remove Ingredient that references Food from recipe step
        i_1.step_set.first().ingredients.remove(i_1)
        assert Food.objects.count() == 10
        assert Ingredient.objects.count() == 10

    # deleting food will succeed because its not part of recipe and delete will cascade to Ingredient
    r = u1_s1.delete(
        reverse(
            DETAIL_URL,
            args={f_1.id}
        )
    )
    assert r.status_code == 204

    with scopes_disabled():
        assert Food.objects.count() == 9
        assert Ingredient.objects.count() == 9


def test_move(u1_s1, obj_tree_1, obj_2, obj_3, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        assert parent.get_num_children() == 1
        assert parent.get_descendant_count() == 2
        assert Food.get_root_nodes().filter(space=space_1).count() == 2

    url = reverse(MOVE_URL, args=[obj_tree_1.id, obj_2.id])

    # move child to new parent, only HTTP put method should work
    r = u1_s1.get(url)
    assert r.status_code == 405
    r = u1_s1.post(url)
    assert r.status_code == 405
    r = u1_s1.delete(url)
    assert r.status_code == 405
    r = u1_s1.put(url)
    assert r.status_code == 200
    with scopes_disabled():
        # django-treebeard bypasses django ORM so object needs retrieved again
        parent = Food.objects.get(pk=parent.id)
        obj_2 = Food.objects.get(pk=obj_2.id)
        assert parent.get_num_children() == 0
        assert parent.get_descendant_count() == 0
        assert obj_2.get_num_children() == 1
        assert obj_2.get_descendant_count() == 2

    # run diagnostic to find problems - none should be found
    with scopes_disabled():
        assert Food.find_problems() == ([], [], [], [], [])


def test_move_errors(u1_s1, obj_tree_1, obj_3, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
    # move child to root
    r = u1_s1.put(reverse(MOVE_URL, args=[obj_tree_1.id, 0]))
    assert r.status_code == 200
    with scopes_disabled():
        assert Food.get_root_nodes().filter(space=space_1).count() == 2

    # attempt to move to non-existent parent
    r = u1_s1.put(
        reverse(MOVE_URL, args=[parent.id, 9999])
    )
    assert r.status_code == 404

    # attempt to move non-existent mode to parent
    r = u1_s1.put(
        reverse(MOVE_URL, args=[9999, parent.id])
    )
    assert r.status_code == 404

    # attempt to move to wrong space
    r = u1_s1.put(
        reverse(MOVE_URL, args=[obj_tree_1.id, obj_3.id])
    )
    assert r.status_code == 404


# TODO: figure out how to generalize this to be all related objects
def test_merge_ingredients(obj_tree_1, u1_s1, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        IngredientFactory.create(food=parent, space=space_1)
        IngredientFactory.create(food=child, space=space_1)
        assert parent.get_num_children() == 1
        assert parent.get_descendant_count() == 2
        assert Ingredient.objects.count() == 2
        assert parent.ingredient_set.count() == 1
        assert obj_tree_1.ingredient_set.count() == 0
        assert child.ingredient_set.count() == 1

    # merge food (with connected ingredient) with children to another food
    r = u1_s1.put(reverse(MERGE_URL, args=[child.id, obj_tree_1.id]))
    assert r.status_code == 200
    with scope(space=space_1):
        # django-treebeard bypasses django ORM so object needs retrieved again
        with pytest.raises(Food.DoesNotExist):
            Food.objects.get(pk=child.id)
        obj_tree_1 = Food.objects.get(pk=obj_tree_1.id)
        assert obj_tree_1.ingredient_set.count() == 1  # now has child's ingredient


def test_merge_shopping_entries(obj_tree_1, u1_s1, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        ShoppingListEntryFactory.create(food=parent,  space=space_1)
        ShoppingListEntryFactory.create(food=child, space=space_1)
        assert parent.get_num_children() == 1
        assert parent.get_descendant_count() == 2
        assert ShoppingListEntry.objects.count() == 2
        assert parent.shopping_entries.count() == 1
        assert obj_tree_1.shopping_entries.count() == 0
        assert child.shopping_entries.count() == 1

    # merge food (with connected shoppinglistentry) with children to another food
    r = u1_s1.put(reverse(MERGE_URL, args=[child.id, obj_tree_1.id]))
    assert r.status_code == 200
    with scope(space=space_1):
        # django-treebeard bypasses django ORM so object needs retrieved again
        with pytest.raises(Food.DoesNotExist):
            Food.objects.get(pk=child.id)
        obj_tree_1 = Food.objects.get(pk=obj_tree_1.id)
        assert obj_tree_1.shopping_entries.count() == 1  # now has child's ingredient


def test_merge(u1_s1,  obj_tree_1, obj_1, obj_3, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        assert parent.get_num_children() == 1
        assert parent.get_descendant_count() == 2
        assert Food.get_root_nodes().filter(space=space_1).count() == 2
        assert Food.objects.count() == 4

    # merge food with no children with another food, only HTTP put method should work
    url = reverse(MERGE_URL, args=[child.id, obj_tree_1.id])
    r = u1_s1.get(url)
    assert r.status_code == 405
    r = u1_s1.post(url)
    assert r.status_code == 405
    r = u1_s1.delete(url)
    assert r.status_code == 405
    r = u1_s1.put(url)
    assert r.status_code == 200
    with scope(space=space_1):
        # django-treebeard bypasses django ORM so object needs retrieved again
        with pytest.raises(Food.DoesNotExist):
            Food.objects.get(pk=child.id)
        obj_tree_1 = Food.objects.get(pk=obj_tree_1.id)
        assert parent.get_num_children() == 1
        assert parent.get_descendant_count() == 1

    # merge food with children with another food
    r = u1_s1.put(reverse(MERGE_URL, args=[parent.id, obj_1.id]))
    assert r.status_code == 200
    with scope(space=space_1):
        # django-treebeard bypasses django ORM so object needs retrieved again
        with pytest.raises(Food.DoesNotExist):
            Food.objects.get(pk=parent.id)
        obj_1 = Food.objects.get(pk=obj_1.id)
        assert obj_1.get_num_children() == 1
        assert obj_1.get_descendant_count() == 1

    # run diagnostic to find problems - none should be found
    with scopes_disabled():
        assert Food.find_problems() == ([], [], [], [], [])


def test_merge_errors(u1_s1, obj_tree_1, obj_3, space_1):
    with scope(space=space_1):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]

    # attempt to merge with non-existent parent
    r = u1_s1.put(
        reverse(MERGE_URL, args=[obj_tree_1.id, 9999])
    )
    assert r.status_code == 404

    # attempt to merge non-existent node to parent
    r = u1_s1.put(
        reverse(MERGE_URL, args=[9999, obj_tree_1.id])
    )
    assert r.status_code == 404
    # attempt to move to wrong space
    r = u1_s1.put(
        reverse(MERGE_URL, args=[obj_tree_1.id, obj_3.id])
    )
    assert r.status_code == 404

    # attempt to merge with child
    r = u1_s1.put(
        reverse(MERGE_URL, args=[parent.id, obj_tree_1.id])
    )
    assert r.status_code == 403

    # attempt to merge with self
    r = u1_s1.put(
        reverse(MERGE_URL, args=[obj_tree_1.id, obj_tree_1.id])
    )
    assert r.status_code == 403


def test_root_filter(obj_tree_1, obj_2, obj_3, u1_s1):
    with scope(space=obj_tree_1.space):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]

    # should return root objects in the space (obj_1, obj_2), ignoring query filters
    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?root=0').content)
    assert len(response['results']) == 2

    with scopes_disabled():
        obj_2.move(parent, node_location)
    # should return direct children of parent (obj_tree_1, obj_2), ignoring query filters
    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?root={parent.id}').content)
    assert response['count'] == 2
    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?root={parent.id}&query={obj_2.name[4:]}').content)
    assert response['count'] == 2


def test_tree_filter(obj_tree_1, obj_2, obj_3, u1_s1):
    with scope(space=obj_tree_1.space):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        obj_2.move(parent, node_location)
    # should return full tree starting at parent (obj_tree_1, obj_2), ignoring query filters
    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?tree={parent.id}').content)
    assert response['count'] == 4
    response = json.loads(u1_s1.get(f'{reverse(LIST_URL)}?tree={parent.id}&query={obj_2.name[4:]}').content)
    assert response['count'] == 4


# This is more about the model than the API - should this be moved to a different test?
@pytest.mark.parametrize("obj_tree_1, field, inherit, new_val", [
    ({'has_category': True, 'inherit': True},  'supermarket_category', True, 'cat_1'),
    ({'has_category': True, 'inherit': False}, 'supermarket_category', False, 'cat_1'),
    ({'ignore_shopping': True, 'inherit': True}, 'ignore_shopping',  True, 'false'),
    ({'ignore_shopping': True, 'inherit': False}, 'ignore_shopping', False, 'false'),
], indirect=['obj_tree_1'])  # indirect=True populates magic variable request.param of obj_tree_1 with the parameter
def test_inherit(request, obj_tree_1, field, inherit, new_val, u1_s1):
    with scope(space=obj_tree_1.space):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]

    new_val = request.getfixturevalue(new_val)
    # if this test passes it demonstrates that inheritance works
    #  when moving to a parent as each food is created with a different category
    assert (getattr(parent, field) == getattr(obj_tree_1, field)) in [inherit, True]
    assert (getattr(obj_tree_1, field) == getattr(child, field)) in [inherit, True]
    # change parent to a new value
    setattr(parent, field, new_val)
    with scope(space=parent.space):
        parent.save()  # trigger post-save signal
        # get the objects again because values are cached
        obj_tree_1 = Food.objects.get(id=obj_tree_1.id)
        child = Food.objects.get(id=child.id)
    # when changing parent value the obj value should be same if inherited
    assert (getattr(obj_tree_1, field) == new_val) == inherit
    assert (getattr(child, field) == new_val) == inherit


# This is more about the model than the API - should this be moved to a different test?
@pytest.mark.parametrize("obj_tree_1, field, inherit, new_val", [
    ({'has_category': True, 'inherit': True, },  'supermarket_category', True, 'cat_1'),
    ({'ignore_shopping': True, 'inherit': True, }, 'ignore_shopping',  True, 'false'),
], indirect=['obj_tree_1'])  # indirect=True populates magic variable request.param of obj_tree_1 with the parameter
def test_ignoreinherit_field(request, obj_tree_1, field, inherit, new_val, u1_s1):
    with scope(space=obj_tree_1.space):
        parent = obj_tree_1.get_parent()
        child = obj_tree_1.get_descendants()[0]
        obj_tree_1.ignore_inherit.add(FoodInheritField.objects.get(field=field))
    new_val = request.getfixturevalue(new_val)

    # change parent to a new value
    setattr(parent, field, new_val)
    with scope(space=parent.space):
        parent.save()  # trigger post-save signal
        # get the objects again because values are cached
        obj_tree_1 = Food.objects.get(id=obj_tree_1.id)
    # inheritance is blocked - should not get new value
    assert getattr(obj_tree_1, field) != new_val

    setattr(obj_tree_1, field, new_val)
    with scope(space=parent.space):
        obj_tree_1.save()  # trigger post-save signal
        # get the objects again because values are cached
        child = Food.objects.get(id=child.id)
    # inherit with child should still work
    assert getattr(child, field) == new_val


# TODO test reset_inheritance
